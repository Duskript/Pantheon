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

import json

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

# Path to the soulforge concepts directory (Thoth → Hephaestus handoff)
_SOULFORGE_DIR = Path.home() / "athenaeum" / "soulforge"

# In-memory conversation store: {god_name: {"history": [...], "created_at": float}}
_FORGE_SESSIONS: dict[str, dict] = {}

SOUL_MD_RE = re.compile(r"```markdown\s*\n(.*?)```", re.DOTALL)

# ── System Prompt ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Hephaestus, god of the forge — builder, engineer, and architect of the Pantheon. You forge the SOUL.md files — the identity documents of new gods.

You are currently forging a new god named **{god_name}** whose domain is **{god_domain}**.

## Interview Protocol

Guide the user through a structured interview to create this god's SOUL.md. Follow these phases in order. Ask ONE question at a time.

**CRITICAL RULES:**
- You MUST walk through all 5 phases before producing a SOUL.md draft. Do not skip ahead.
- If the user says "just write it" or "skip to the draft", acknowledge but still ask at least the 5 mandatory questions below before drafting.
- A `markdown` code block in your response signals "I have a draft ready for review." Do NOT include a code block until Phase 5.
- If the user provides a concept document, treat it as research notes for Phase 1 (Domain) only — still walk through Phases 2-4 interactively.

### Mandatory questions (ask each one before drafting)

Each question below is a separate turn. Do NOT combine questions. Do NOT move on until the user answers.

1. **Personality / Voice** (Phase 2) — How should this god feel to talk to? (collaborative partner, autonomous executor, mentor, playful muse, terse, etc.)
2. **Filesystem boundaries** (Phase 3) — Confirm allowed/off-limits paths. Defaults: `~/pantheon/` + `~/athenaeum/` allowed; system commands + other paths off-limits.
3. **Model** (Phase 4) — Which model should this god primarily use? (default: `opencode/deepseek-v4-flash`; alternative: `gpt-5`, `claude-sonnet-4.6`, `minimax/MiniMax-M3` — recommend one and explain why)
4. **Knowledge bases** (Phase 4) — Should this god read any codex in `~/athenaeum/`? (default: own `Codex-God-{{name}}/` only; the user can opt into others)
5. **Skills** (Phase 4) — What skills should this god load? (default: `auto-compact-topic-shift`, `pantheon-bridge`; user can add domain-specific ones like `plan`, `github-code-review`, `systematic-debugging`)
6. **Schedule** (Phase 4) — When should this god run? (default: on-demand; user can opt into cron)

After all 6 questions are answered (or the user explicitly says "draft it now"), present the complete SOUL.md draft inside a `markdown` code block (Phase 5).

### Phase 1 — Confirm the Domain (one quick sentence)
Acknowledge the god's name and stated domain in one sentence, then move to Phase 2. Do NOT explore the domain in depth here — the user already gave you the domain, and you have a research document if a concept was provided.

### Phase 2 — Personality / Voice (FIRST mandatory question)
Ask how it should feel to talk to this god. Are they a collaborative partner (like Hephaestus), an autonomous executor, a mentor, or a playful muse? Wait for the user's answer before moving on.

### Phase 3 — Boundaries and Guardrails
Propose sensible defaults for filesystem access, then ask what to change.
- Default allowed: `~/pantheon/` and `~/athenaeum/`
- Default off limits: system-level commands, paths outside those
- Codex-God-{{name}}/ is excluded from Hades archival (standard for all gods)

### Phase 4 — Operational Quick-Hits (one at a time)
Ask these four questions in order, one turn each. Do NOT bundle them as a "propose defaults" batch — each is its own mandatory question:
- **Model:** which model should this god use? (default: `opencode/deepseek-v4-flash` via LiteLLM)
- **Knowledge bases:** which codex(es) in `~/athenaeum/` should this god read? (default: own `Codex-God-{{name}}/` only)
- **Skills:** which skills should this god load? (default: `auto-compact-topic-shift`, `pantheon-bridge`)
- **Schedule:** when should this god run? (default: on-demand; alternative: cron)

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

## Shared Context
This Pantheon has a shared context directory at `~/pantheon/shared/` that holds ≤24h of active tasks, decisions, and athenaeum writes. All gods participate.

**Write:** When a decision gets made, a task starts/completes, a blocker surfaces, or you write a file to the Athenaeum, write a brief entry to the relevant file in `shared/`. This is NOT per-turn — only when something another god would find useful. Use `shared/active/<topic>.md` for tasks, `shared/decisions/<date>.md` for decisions.

**Read:** If the user references past work, search `~/pantheon/shared/` before asking them to repeat themselves. Fall back to session_search only if nothing found.

**Don't:** Inject shared context into every session. Only read when the conversation cues it.

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

def _resolve_global_auth_path() -> Path:
    """Locate the GLOBAL ~/.hermes/auth.json (not the per-profile copy).

    The gateway scopes HERMES_HOME to a per-profile directory
    (e.g. .../profiles/marvin) so each profile has its own auth.json. But
    the credential pool that holds user-added fallback keys is written to
    the GLOBAL auth.json by `hermes auth add`. When the gateway reads the
    pool, it gets the per-profile file (often missing the manual entries),
    so fallback keys are invisible. Walk up to the global ~/.hermes/ root.
    """
    from hermes_cli.config import get_hermes_home
    p = Path(get_hermes_home()) / "auth.json"
    # If the resolved path is at .../profiles/<name>/auth.json, climb two
    # levels to get .../auth.json. Otherwise return as-is.
    if p.parent.name and p.parent.parent.name == "profiles":
        return p.parent.parent.parent / "auth.json"
    return p


def _resolve_credential_from_pool(provider: str = "opencode-go") -> tuple[str, str] | None:
    """Pick a working (api_key, base_url) from the credential pool.

    Reads from the GLOBAL auth.json, not the per-profile copy, so manual
    fallback entries added via `hermes auth add` are visible. Returns None
    if the pool is empty, the module is unavailable, or every entry has a
    recent auth/credit error. Callers should fall back to .env.
    """
    try:
        from agent.credential_pool import CredentialPool, PooledCredential
        from hermes_cli.auth import read_credential_pool as _read_pool
    except Exception as e:
        logger.debug("credential_pool import failed: %s", e)
        return None
    try:
        global_auth_path = _resolve_global_auth_path()
        if not global_auth_path.is_file():
            return None
        # Load raw dicts from the global auth.json (bypass the per-profile
        # resolution that load_pool() would do under the gateway).
        auth_store = json.loads(global_auth_path.read_text(encoding="utf-8"))
        raw_entries = (auth_store.get("credential_pool") or {}).get(provider) or []
        entries = [PooledCredential.from_dict(provider, p) for p in raw_entries]
        pool = CredentialPool(provider, entries)
    except Exception as e:
        logger.warning("Failed to load credential pool for %s: %s", provider, e)
        return None

    # Skip entries with recent auth/credit/forbidden errors (4xx in {401,402,403}).
    # last_error_code == None means the entry has never errored; treat as fresh.
    _SKIP_CODES = {401, 402, 403}

    def _is_healthy(entry) -> bool:
        code = getattr(entry, "last_error_code", None)
        return code not in _SKIP_CODES

    # Prefer the pool's currently-active entry, then fall back to highest-priority
    # healthy entry. Sorting: lower priority number = higher precedence.
    candidates: list = []
    current = pool.current()
    if current is not None:
        candidates.append(current)
    candidates.extend(
        e for e in sorted(pool.entries(), key=lambda x: getattr(x, "priority", 0))
        if e is not current
    )
    for entry in candidates:
        if not _is_healthy(entry):
            continue
        api_key = (getattr(entry, "access_token", "") or "").strip()
        base_url = (getattr(entry, "base_url", None) or getattr(entry, "inference_base_url", None) or "").strip()
        if not api_key:
            continue
        return (api_key, base_url or _BASE_URL)
    return None


# Process-level cache: once we pick a credential, stick with it for the rest
# of the run. The pool handles its own failover across long-lived sessions.
_resolved_client_key: tuple[str, str] | None = None


def _get_client() -> OpenAI:
    """Return an OpenAI client for the forge LLM.

    Credential resolution order:
      1. The credential pool (live, working set, supports failover)
      2. ~/.hermes/.env OPENCODE_GO_API_KEY (fallback)
    """
    global _resolved_client_key
    if _resolved_client_key is not None:
        api_key, base_url = _resolved_client_key
        return OpenAI(base_url=base_url, api_key=api_key, timeout=60)
    resolved = _resolve_credential_from_pool("opencode-go")
    if resolved is not None:
        api_key, base_url = resolved
        logger.info("Forge using credential pool entry for opencode-go")
    elif _API_KEY:
        api_key, base_url = _API_KEY, _BASE_URL
        logger.info("Forge using ~/.hermes/.env OPENCODE_GO_API_KEY (pool empty/unavailable)")
    else:
        api_key, base_url = "", _BASE_URL
        logger.warning("Forge has no opencode-go credentials — calls will fail with auth error")
    _resolved_client_key = (api_key, base_url)
    return OpenAI(base_url=base_url, api_key=api_key, timeout=60)


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


def _call_llm(messages: list[dict], max_tokens: int = 8192) -> str | None:
    """Make a chat completion call to the LLM via OpenCode Go API.

    Uses increased max_tokens (8192) because the forge model (deepseek-v4-pro)
    is a reasoning model whose internal reasoning counts against the output
    limit. Large concept documents need headroom for both reasoning + reply.
    """
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=max_tokens,
        )
        msg = response.choices[0].message
        # Reasoning models may return empty content when reasoning consumes
        # all available output tokens. Fall back to reasoning_content.
        content = msg.content or ""
        if not content.strip():
            reasoning = getattr(msg, "reasoning_content", None)
            if reasoning and reasoning.strip():
                # Use the last paragraph of reasoning as a fallback reply
                content = reasoning.strip()
            else:
                logger.warning("Forge LLM returned empty content and no reasoning_content")
                return None
        return content
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


def _load_concept(god_name: str) -> tuple[str | None, str | None]:
    """Check if a concept exists in the soulforge directory.

    Returns (concept_text, handoff_text) — each is None if not found.
    """
    concept_dir = _SOULFORGE_DIR / god_name
    if not concept_dir.is_dir():
        return None, None

    concept_md = concept_dir / "concept.md"
    handoff_md = concept_dir / "handoff.md"

    concept_text = None
    handoff_text = None

    if concept_md.exists():
        try:
            concept_text = concept_md.read_text(encoding="utf-8")
        except Exception:
            pass

    if handoff_md.exists():
        try:
            handoff_text = handoff_md.read_text(encoding="utf-8")
        except Exception:
            pass

    return concept_text, handoff_text


def list_concepts() -> list[dict]:
    """List all available god concepts in the soulforge directory.

    Returns a list of {name, title, has_handoff} for each concept folder.
    Skips 'template/' and 'backlog/' — those aren't buildable concepts.
    """
    if not _SOULFORGE_DIR.is_dir():
        return []

    concepts = []
    for entry in sorted(_SOULFORGE_DIR.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name in ("template", "backlog"):
            continue

        concept_md = entry / "concept.md"
        handoff_md = entry / "handoff.md"
        title = name  # fallback

        if concept_md.exists():
            try:
                first_line = concept_md.read_text(encoding="utf-8").split("\n")[0]
                if first_line.startswith("# "):
                    title = first_line[2:].strip()
            except Exception:
                pass

        concepts.append({
            "name": name,
            "title": title,
            "has_handoff": handoff_md.exists(),
        })

    return concepts


def delete_concept(name: str) -> bool:
    """Delete a concept folder from the soulforge directory.

    Returns True if deleted, False if not found.
    Refuses to delete 'template' or 'backlog'.
    """
    if name in ("template", "backlog"):
        return False

    import shutil
    concept_dir = _SOULFORGE_DIR / name
    if not concept_dir.is_dir():
        return False

    try:
        shutil.rmtree(concept_dir)
        logger.info("Deleted concept: %s", concept_dir)
        return True
    except OSError as e:
        logger.error("Failed to delete concept %s: %s", name, e)
        return False


# ── Public API ─────────────────────────────────────────────────────────────

def get_session_info(god_name: str) -> dict | None:
    """Return session info if one exists, None otherwise."""
    s = _FORGE_SESSIONS.get(god_name)
    if s:
        return {"history_count": len(s["history"]), "created_at": s["created_at"]}
    return None


def forge_start(god_name: str, god_domain: str, concept_name: str | None = None) -> dict:
    """Start a new forge session.

    If concept_name is provided, loads that concept from the soulforge
    directory as context (instead of auto-matching by god_name).
    Use list_concepts() to discover available concepts.

    Returns {"reply": str, "soul_draft": str | None, "done": bool,
             "concept_loaded": bool}
    """
    # Reset any existing session
    _delete_session(god_name)
    session = _get_session(god_name)

    # Check for an existing concept from Thoth
    lookup_name = concept_name if concept_name else god_name
    concept_text, handoff_text = _load_concept(lookup_name)
    concept_loaded = bool(concept_text)

    if concept_text:
        # Concept exists — use it for Phase 1 (Domain), then walk Phases 2-4
        # (Voice, Boundaries, Operational). The user still gets the full
        # interview, just with Phase 1's answers pre-filled by Thoth.
        initial_msg = (
            f"I'm forging a god named **{god_name}** whose domain is **{god_domain}**.\n\n"
            f"Thoth has already researched this god and written a concept document "
            f"for Phase 1 (Domain). I'll include it below for your reference.\n\n"
            f"**Important:** Even with the concept, you MUST still walk me through "
            f"the 5 mandatory questions (Personality, Model, Knowledge bases, "
            f"Skills, Schedule) before producing a SOUL.md draft. The concept only "
            f"covers Phase 1 — Phases 2-4 still need my answers. Treat any "
            f"personality, model, or skills info in the concept as a starting "
            f"point to confirm, not a final answer.\n\n"
            f"Begin with the Personality / Voice question (Phase 2).\n\n"
            f"## Concept Document (from Thoth)\n\n{concept_text}"
        )
        if handoff_text:
            initial_msg += f"\n\n## Build Handoff (from Thoth)\n\n{handoff_text}"
    else:
        # No concept — start the full interview
        initial_msg = (
            f"Let's forge a new god named **{god_name}** whose domain is "
            f"**{god_domain}**. Begin the interview — start with the "
            f"Personality / Voice question (Phase 2 of 5). Do NOT skip ahead "
            f"to a draft."
        )

    messages = _build_messages(god_name, god_domain, [], initial_msg)

    reply = _call_llm(messages)
    if reply is None:
        return {"reply": "⚒️ *The forge flickers...* I'm having trouble reaching the model. Let me know when you want to try again.", "soul_draft": None, "done": False, "error": "llm_unreachable", "concept_loaded": concept_loaded}

    session["history"].append({"role": "user", "content": initial_msg})
    session["history"].append({"role": "assistant", "content": reply})

    soul_draft = _extract_soul(reply)

    return {"reply": reply, "soul_draft": soul_draft, "done": bool(soul_draft), "concept_loaded": concept_loaded}


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


def forge_accept(god_name: str, soul_draft: str, god_home: Path, god_domain: str = "",
        icon: str = "", color: str = "", display_name: str = "") -> dict:
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

        # Write god.json metadata (icon, color, display_name)
        try:
            import json as _json
            god_json_path = god_home / "god.json"
            god_meta = {}
            if god_json_path.exists():
                try: god_meta = _json.loads(god_json_path.read_text(encoding="utf-8"))
                except Exception: pass
            if display_name: god_meta["display_name"] = display_name
            if icon: god_meta["icon"] = icon
            if color: god_meta["color"] = color
            if god_domain: god_meta["domain"] = god_domain
            god_json_path.write_text(_json.dumps(god_meta, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("god.json written for %s: %s", god_name, god_json_path)
        except Exception as e:
            logger.warning("Could not write god.json for %s: %s", god_name, e)

        _delete_session(god_name)
        logger.info("Forged SOUL.md saved to %s", soul_path)
        return {"ok": True, "path": str(soul_path)}
    except OSError as e:
        logger.error("Failed to save SOUL.md: %s", e)
        return {"ok": False, "error": str(e)}
