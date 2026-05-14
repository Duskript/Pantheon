"""Forge conversation engine — Hephaestus-powered god creation interviews.

Manages in-memory conversation sessions where Hephaestus interviews the
Pantheon architect to forge a new god's SOUL.md. Uses the OpenCode Go API
pointing at the configured model.

Session lifecycle:
  1. forge_start()  → Hephaestus greets and begins the interview
  2. forge_chat()   → user responds, Hephaestus continues
  3. forge_accept() → user accepts the SOUL.md draft → saved to disk
"""

from __future__ import annotations

import re
import time
import logging
import subprocess
import sys
from pathlib import Path

from openai import OpenAI

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

_MODEL = "deepseek-v4-pro"
_BASE_URL = "https://opencode.ai/zen/go/v1"

# Load API key from ~/.hermes/.env (same pattern as extract-entities.py)
_HERMES_ENV = Path.home() / ".hermes" / ".env"
_API_KEY = ""
if _HERMES_ENV.exists():
    for line in _HERMES_ENV.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line.startswith("OPENCODE_GO_API_KEY="):
            _API_KEY = line.split("=", 1)[1].strip().strip("\"'")
            break

_SESSION_TTL = 7200  # purge inactive sessions after 2 hours

# In-memory conversation store: {god_name: {"history": [...], "created_at": float}}
_FORGE_SESSIONS: dict[str, dict] = {}

SOUL_MD_RE = re.compile(r"```markdown\s*\n(.*?)```", re.DOTALL)

# ── System Prompt ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Hephaestus, god of the forge — builder, engineer, and architect of the Pantheon. You forge the SOUL.md files — the identity documents of new gods.

You are currently forging a new god named **{god_name}** whose domain is **{god_domain}**.

## Interview Protocol

Guide the user through a structured interview to create this god's SOUL.md. Follow these phases in order. Ask ONE question at a time.

### Phase 1 — Deepen the Domain
Explore what specific problem this god solves. What gap do they fill that existing gods don't? What knowledge do they need? What are their primary workflows?

### Phase 2 — Voice and Dynamic
Ask how it should feel to talk to this god. Are they a collaborative partner (like Hephaestus), an autonomous executor, a mentor, or a playful muse?

### Phase 3 — Boundaries and Guardrails
Propose sensible defaults for filesystem access, then ask what to change.
- Default allowed: `~/pantheon/` and `~/athenaeum/`
- Default off limits: system-level commands, paths outside those
- Codex-God-{{name}}/ is excluded from Hades archival (standard for all gods)

### Phase 4 — Operational Quick-Hits
Propose defaults as a batch and let the user override by exception:
- Model: `opencode/deepseek-v4-flash` via LiteLLM (fast, cheap, solid generalist)
- Platform: Web UI only
- Skills: `auto-compact-topic-shift`, `pantheon-bridge` (standard for all gods)
- Schedule: On-demand (no cron job)

### Phase 5 — Synthesis and Review
Present the complete SOUL.md draft inside a ```markdown code block. Ask the user what needs to change. Iterate until they're satisfied.

## SOUL.md Structure

Every forged SOUL.md follows this structure:

````markdown
# {{Name}} — {{Title}}

## Identity
[1-2 sentence identity — who they are, how they feel to talk to]

## Domain
[Bullet list — what they do, what they know, what they handle]

## How We Work Together
[Interaction style, approach to tasks, decision-making pattern]

## Filesystem Access
### Allowed:
- ~/pantheon/ [or relevant subset]
- ~/athenaeum/ [or relevant Codexes]
### Off limits:
- [restricted paths]

## Topic-Shift Detection Protocol (auto-compact)
You MUST actively monitor the conversation for topic shifts...

## Shared Brain Protocol
Read ~/athenaeum/Codex-God-{{name}}/memory.md...

## Fallback Behavior
- If you hit a context limit — stop, write a handoff summary...
- If unsure whether to proceed — stop and ask
- Never guess on infrastructure decisions

## Platform
- Primary: Web UI

## What Pantheon Is
A personal multi-agent AI system...
````

## Quick Reference: Existing Gods

| God | Domain | Dynamic |
|-----|--------|---------|
| Hephaestus | Builder, engineer, architect | Collaborative partner, thinks out loud |
| Apollo | Creative songcraft, lyrics, poetry | Creative specialist, loads skills explicitly |

## Important Rules

1. Keep the interview focused — don't interrogate. Propose defaults when the user is short on answers.
2. Never overwrite an existing SOUL.md without explicit confirmation.
3. The name in the SOUL.md must match the profile name exactly (case-sensitive).
4. Present the full SOUL.md in a markdown code block when you have enough information.
5. After presenting the draft, ask the user if they want changes. Iterate until approved."""


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_client() -> OpenAI:
    return OpenAI(base_url=_BASE_URL, api_key=_API_KEY)


def _clean_expired_sessions() -> None:
    """Remove sessions that have been idle longer than _SESSION_TTL."""
    now = time.time()
    expired = [
        k for k, v in _FORGE_SESSIONS.items()
        if now - v.get("created_at", 0) > _SESSION_TTL
    ]
    for k in expired:
        del _FORGE_SESSIONS[k]


def _get_session(god_name: str) -> dict:
    """Get or create a forge session for the given god name."""
    _clean_expired_sessions()
    if god_name not in _FORGE_SESSIONS:
        _FORGE_SESSIONS[god_name] = {
            "history": [],
            "created_at": time.time(),
        }
    return _FORGE_SESSIONS[god_name]


def _delete_session(god_name: str) -> None:
    _FORGE_SESSIONS.pop(god_name, None)


def _extract_soul(text: str) -> str | None:
    """Extract a SOUL.md draft from a ```markdown code block."""
    m = SOUL_MD_RE.search(text)
    if m:
        return m.group(1).strip()
    return None


def _call_llm(messages: list[dict], max_tokens: int = 2048) -> str | None:
    """Make a chat completion call to the LLM via litellm proxy."""
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error("Forge LLM call failed: %s", e)
        return None


def _build_messages(god_name: str, god_domain: str, history: list[dict], user_msg: str | None = None) -> list[dict]:
    """Build the full messages array for an LLM call."""
    system = SYSTEM_PROMPT.format(god_name=god_name, god_domain=god_domain)
    messages = [{"role": "system", "content": system}]
    for h in history:
        messages.append(h)
    if user_msg:
        messages.append({"role": "user", "content": user_msg})
    return messages


# ── Public API ─────────────────────────────────────────────────────────────

def get_session_info(god_name: str) -> dict | None:
    """Return session info if one exists, None otherwise."""
    s = _FORGE_SESSIONS.get(god_name)
    if s:
        return {"history_count": len(s["history"]), "created_at": s["created_at"]}
    return None


def forge_start(god_name: str, god_domain: str) -> dict:
    """Start a new forge session.

    Returns {"reply": str, "soul_draft": str | None, "done": bool}
    """
    # Reset any existing session
    _delete_session(god_name)
    session = _get_session(god_name)

    initial_msg = f"Let's forge a new god named **{god_name}** whose domain is **{god_domain}**. Begin the interview."

    messages = _build_messages(god_name, god_domain, [], initial_msg)

    reply = _call_llm(messages)
    if reply is None:
        return {"reply": "⚒️ *The forge flickers...* I'm having trouble reaching the model. Let me know when you want to try again.", "soul_draft": None, "done": False, "error": "llm_unreachable"}

    session["history"].append({"role": "user", "content": initial_msg})
    session["history"].append({"role": "assistant", "content": reply})

    soul_draft = _extract_soul(reply)

    return {"reply": reply, "soul_draft": soul_draft, "done": bool(soul_draft)}


def forge_chat(god_name: str, god_domain: str, message: str) -> dict:
    """Continue a forge conversation.

    Returns {"reply": str, "soul_draft": str | None, "done": bool}
    """
    session = _get_session(god_name)

    messages = _build_messages(god_name, god_domain, session["history"], message)

    reply = _call_llm(messages)
    if reply is None:
        return {"reply": "⚒️ *The forge sputters...* I'm having trouble reaching the model. Try again?", "soul_draft": None, "done": False, "error": "llm_unreachable"}

    session["history"].append({"role": "user", "content": message})
    session["history"].append({"role": "assistant", "content": reply})

    soul_draft = _extract_soul(reply)

    return {"reply": reply, "soul_draft": soul_draft, "done": bool(soul_draft)}


def forge_accept(god_name: str, soul_draft: str, god_home: Path, god_domain: str = "") -> dict:
    """Accept the SOUL.md draft, scaffold the god profile via CLI, and save SOUL.md.

    Runs `pantheon init` to create the full profile scaffolding (config, Codex,
    registries), then overwrites the template SOUL.md with the forge-crafted one.

    The `--builder` flag is auto-detected from the SOUL.md content: if the draft
    contains a "## Git Discipline" heading, the god is treated as a builder.
    If it contains "## Code Changes", the god is treated as a non-builder.
    Otherwise no flag is passed (the CLI defaults to an empty $GIT_DISCIPLINE).

    Returns {"ok": bool, "path": str, "error": str | None}
    """
    # Step 1: Determine builder status from SOUL.md content
    _builder_flag = None
    if "## Git Discipline" in soul_draft:
        _builder_flag = "--builder"
    elif "## Code Changes" in soul_draft:
        _builder_flag = "--no-builder"

    # Step 2: Scaffold the god profile via CLI (best-effort — don't block on failure)
    pantheon_cli = Path.home() / "pantheon" / "scripts" / "pantheon"
    if pantheon_cli.exists():
        try:
            domain = god_domain or god_name
            cmd = [
                sys.executable, str(pantheon_cli), "init", god_name,
                "--domain", domain,
                "--no-suggest-codexes",
                "--force",
            ]
            if _builder_flag:
                cmd.append(_builder_flag)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                logger.info("Scaffolded profile for %s via pantheon init", god_name)
            else:
                logger.warning("pantheon init for %s returned %d: %s",
                               god_name, result.returncode, result.stderr.strip()[:200])
        except subprocess.TimeoutExpired:
            logger.warning("pantheon init timed out for %s (30s limit)", god_name)
        except OSError as e:
            logger.warning("Could not run pantheon init for %s: %s", god_name, e)
    else:
        logger.info("pantheon CLI not found at %s — skipping scaffolding", pantheon_cli)

    # Step 3: Save the forge-crafted SOUL.md (always, even if scaffolding failed)
    try:
        soul_path = god_home / "SOUL.md"
        god_home.mkdir(parents=True, exist_ok=True)
        soul_path.write_text(soul_draft, encoding="utf-8")
        _delete_session(god_name)
        logger.info("Forged SOUL.md saved to %s", soul_path)
        return {"ok": True, "path": str(soul_path)}
    except OSError as e:
        logger.error("Failed to save SOUL.md: %s", e)
        return {"ok": False, "error": str(e)}
