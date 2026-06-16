"""
B5: Tier A+ — opt-in LLM extraction for richer post-session learning.

Moved from `lib/ichor_tier_a_plus.py` into the ichor package on
2026-06-12 as part of the package refactor (Thoth answered Q1
with "inside the package, clean break"). Public surface unchanged:
`extract_llm_rich()`, `_call_llm()`, `_write_to_pantheon()`,
`_resolve_llm_provider()`, `_delete_warm_pref()`, `extract_llm_rich_with_disabled_fallback()`.

Spec: ~/athenaeum/Codex-God-thoth/research/openviking-vs-ichor-comparison/build-brief.md §P5
      ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §B5

`extract_llm_rich(session_summary, god_name)` fires a single LLM call
on session end, parses the response into 4 fields, and writes each to
the right pantheon:// location. Default behavior (tier_a_plus=false)
is a complete no-op — same as the regex-only Tier A.

Why opt-in: an LLM call per session is a real cost (~$0.001-0.01 per
session depending on provider, plus latency). The spec explicitly says
"Default = off. Only gods with `tier_a_plus=true` pay the cost." This
matches the same philosophy as the rest of the system: bias toward
not adding cost unless explicitly enabled.

The LLM call is to whatever provider is configured for the god. If no
provider is configured, the call is skipped gracefully (returns empty
result, no exception).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("lib.ichor.llm")  # was "ichor_tier_a_plus" pre-2026-06-12


_HOME = Path.home()
_ICHOR_DB = _HOME / ".hermes" / "ichor.db"
_GODS_YAML = Path("/home/konan/pantheon/gods/gods.yaml")
_ATHENAEUM_ROOT = _HOME / "athenaeum"

RICH_FIELDS = (
    "learned_preferences",
    "used_resources",
    "skills_applied",
    "task_memories",
)

# Where each rich field gets written:
#   learned_preferences → pantheon://warm/preference/<name>
#   used_resources      → tracked by ichor_score (no separate write; just
#                          recorded in the response for downstream consumption)
#   skills_applied      → pantheon://gods/{god}/skills/<name>.md
#   task_memories       → pantheon://warm/insight/<name> (insight is the
#                          best-fit existing category for "things learned
#                          in this session that aren't preferences")
_WRITE_TARGETS = {
    "learned_preferences": ("warm", "preference"),
    "used_resources": None,  # no write — just returned
    "skills_applied": ("god_skills", None),  # god-specific path
    "task_memories": ("warm", "insight"),
}


# ---------------------------------------------------------------------------
# Config: tier_a_plus + provider resolution
# ---------------------------------------------------------------------------

def _read_gods_yaml() -> Dict[str, Any]:
    """Tiny YAML reader — we only need a flat `gods: { name: {...} }` map.

    Avoids pulling in PyYAML as a dependency. If the file is missing
    or malformed, returns an empty dict (all gods default to off).
    """
    if not _GODS_YAML.exists():
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        # Fallback: parse the simple structure manually
        return _parse_gods_yaml_simple(_GODS_YAML.read_text())
    try:
        data = yaml.safe_load(_GODS_YAML.read_text())
        if not isinstance(data, dict):
            return {}
        return data.get("gods", {}) or {}
    except Exception as e:
        logger.warning("could not parse gods.yaml: %s", e)
        return {}


def _parse_gods_yaml_simple(text: str) -> Dict[str, Any]:
    """Minimal YAML parser for gods.yaml — handles the flat structure we use."""
    gods: Dict[str, Dict[str, Any]] = {}
    current_god: Optional[str] = None
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        # Top-level 'gods:' is at column 0
        if line == "gods:":
            continue
        # God names are at column 2, ending with ':'
        m = re.match(r"^  ([a-z_-]+):$", line)
        if m:
            name = m.group(1)
            if name:
                gods[name] = {}
                current_god = name
            continue
        # God-level settings are at column 4
        if current_god and line.startswith("    "):
            stripped = line.strip()
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                v = v.strip()
                # Strip surrounding quotes if present
                if v.startswith('"') and v.endswith('"'):
                    v = v[1:-1]
                gods[current_god][k.strip()] = v
    return gods


def _is_tier_a_plus_enabled(god_name: str) -> bool:
    """Read tier_a_plus for `god_name` from gods.yaml. Hot-reload: re-reads each call."""
    gods = _read_gods_yaml()
    god_cfg = gods.get(god_name, {})
    raw = str(god_cfg.get("tier_a_plus", "")).lower().strip()
    return raw in ("true", "1", "yes", "on")


def _resolve_llm_provider(god_name: str) -> Optional[Dict[str, Any]]:
    """Find the LLM provider for this god. Returns None if unavailable.

    Resolution order:
      1. god's own `llm_provider` field in gods.yaml
      2. god's own `provider` field
      3. Hermes profile's `model.default` in ~/.hermes/profiles/<god>/config.yaml
      4. The active profile (this Marvin session)
    """
    gods = _read_gods_yaml()
    god_cfg = gods.get(god_name, {})

    # Try god's explicit provider
    provider_name = god_cfg.get("llm_provider") or god_cfg.get("provider")
    if provider_name:
        return _load_provider_config(str(provider_name))

    # Fall back to the active profile
    active = _HOME / ".hermes" / "profiles" / god_name / "config.yaml"
    if active.exists():
        try:
            import yaml
            data = yaml.safe_load(active.read_text())
            if isinstance(data, dict):
                model = data.get("model", {})
                if isinstance(model, dict):
                    p = model.get("provider") or model.get("default")
                    if p:
                        return _load_provider_config(str(p))
        except Exception as e:
            logger.debug("could not read %s: %s", active, e)
    return None


def _load_provider_config(provider_name: str) -> Optional[Dict[str, Any]]:
    """Load a provider's config from Hermes."""
    config_path = _HOME / ".hermes" / "config.yaml"
    if not config_path.exists():
        return None
    try:
        import yaml
        data = yaml.safe_load(config_path.read_text())
        if not isinstance(data, dict):
            return None
        providers = data.get("providers", {}) or {}
        return providers.get(provider_name)
    except Exception as e:
        logger.debug("could not read Hermes config: %s", e)
        return None


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_llm(prompt: str, provider_cfg: Dict[str, Any],
              model: Optional[str] = None,
              timeout: float = 180.0) -> str:
    """Single LLM call. Returns the raw text response.

    Uses the OpenAI-compatible chat completions endpoint that most
    providers expose. Times out after 180s.

    180s (3 min) is the floor for deepseek-v4-flash on dense batches at
    max_tokens=8000. The model can legitimately take 60-130s to respond
    on a 25-event prompt; 30s was a leftover from when max_tokens=800
    and the model finished in <10s. Bumped 2026-06-12 after the L2
    full-corpus loop timed out on 3/3 retries at the 30s default.
    """
    api_base = provider_cfg.get("api", "").rstrip("/")
    if not api_base:
        raise ValueError("provider has no api base URL")
    model_name = model or provider_cfg.get("default_model", "")
    if not model_name:
        raise ValueError("no model specified for provider")
    api_key = provider_cfg.get("api_key", "") or os.environ.get(
        f"{provider_cfg.get('name', 'PROVIDER').upper()}_API_KEY", ""
    )

    url = f"{api_base}/chat/completions"
    body = json.dumps({
        "model": model_name,
        "messages": [
            {"role": "system",
             "content": "You are a careful analyst. Output ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 8000,
        # Disable reasoning mode for thinking models (deepseek-v4-flash, kimi-k2
        # thinking, etc.). Without this, the model uses its entire token budget
        # for hidden chain-of-thought reasoning and emits 0 chars of visible
        # content, leaving the L2 extractor with empty responses. Per deepseek
        # API docs: api-docs.deepseek.com/guides/thinking_mode. Discovered
        # 2026-06-12 during the L2 full-corpus run.
        "thinking": {"type": "disabled"},
        "temperature": 0.2,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    # Cloudflare (which fronts opencode.ai and many other LLM gateways)
    # rejects requests with no User-Agent as bot traffic (error 1010).
    # Set a recognizable UA so the package works against CF-fronted
    # endpoints out of the box. Discovered 2026-06-12 while running
    # the L2 full-corpus loop — the opencode-go endpoint returned 403
    # until we added this header.
    req.add_header("User-Agent", "pantheon-ichor/1.0 (lib.ichor.llm)")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choices = data.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "") or ""


# ---------------------------------------------------------------------------
# Prompt + parsing
# ---------------------------------------------------------------------------

def _build_prompt(session_summary: str, god_name: str) -> str:
    """Build the prompt asking for a structured JSON response."""
    return f"""Analyze this session summary from the god '{god_name}' and extract four categories of insights. Output ONLY valid JSON, no prose, no markdown fences.

Session summary:
\"\"\"
{session_summary}
\"\"\"

Return JSON with exactly these four fields (each a list of short strings):
  - learned_preferences: new user/god preferences observed (e.g. "prefers concise replies")
  - used_resources: tools, files, APIs touched in this session
  - skills_applied: skills or techniques the god used (e.g. "tiered retrieval", "patch-based editing")
  - task_memories: short factual notes worth remembering (NOT preferences)

Example output:
{{"learned_preferences": ["..."], "used_resources": ["..."], "skills_applied": ["..."], "task_memories": ["..."]}}
"""


def _empty_rich_result() -> Dict[str, List[str]]:
    return {field: [] for field in RICH_FIELDS}


def _parse_rich_response(raw: str) -> Dict[str, List[str]]:
    """Parse the LLM's response into a structured dict.

    Tolerant: handles missing fields, extra whitespace, and JSON inside
    prose. Returns the empty result on any parse error.
    """
    if not raw or not raw.strip():
        return _empty_rich_result()

    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        # Drop first line (```json) and last ```
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

    # Find the first { and last } (in case the LLM wrapped JSON in prose)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("rich extraction: could not parse JSON: %s", e)
        return _empty_rich_result()

    if not isinstance(data, dict):
        return _empty_rich_result()

    result: Dict[str, List[str]] = _empty_rich_result()
    for field in RICH_FIELDS:
        v = data.get(field, [])
        if isinstance(v, list):
            # Coerce to strings, drop empty
            result[field] = [str(x) for x in v if str(x).strip()]
    return result


# ---------------------------------------------------------------------------
# Writing to pantheon://
# ---------------------------------------------------------------------------

def _write_to_pantheon(result: Dict[str, List[str]], god_name: str) -> None:
    """Write extracted items to their pantheon:// destinations."""
    for field, items in result.items():
        target = _WRITE_TARGETS.get(field)
        if target is None:
            continue  # used_resources is return-only
        if target[0] == "warm":
            _write_warm_entities(field, items, target[1])
        elif target[0] == "god_skills":
            _write_god_skills(god_name, items)


def _write_warm_entities(field: str, items: List[str], category: str) -> None:
    """Write a list of items to warm_entities with the given category."""
    if not items or not _ICHOR_DB.exists():
        return
    con = sqlite3.connect(_ICHOR_DB)
    try:
        for item in items:
            try:
                con.execute(
                    "INSERT INTO warm_entities "
                    "(category, name, value, importance, trust, maturity, "
                    " created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                    (
                        category,
                        item,
                        item,  # value = name (no separate detail field)
                        60.0,  # moderate importance
                        0.7,
                        "fresh",
                    ),
                )
            except sqlite3.IntegrityError:
                # Already exists — that's fine, no need to overwrite
                pass
        con.commit()
    finally:
        con.close()


def _delete_warm_pref(name: str) -> None:
    """Remove a warm_entity by name (test cleanup helper)."""
    if not _ICHOR_DB.exists():
        return
    con = sqlite3.connect(_ICHOR_DB)
    try:
        con.execute(
            "DELETE FROM warm_entities WHERE name = ? AND category = 'preference'",
            (name,),
        )
        con.commit()
    finally:
        con.close()


def _write_god_skills(god_name: str, items: List[str]) -> None:
    """Write each skill to the god's codex as a markdown file."""
    if not items:
        return
    # Find the god's codex dir
    codex_dir = _ATHENAEUM_ROOT / f"Codex-God-{god_name.capitalize()}"
    if not codex_dir.exists():
        # Fall back to the lowercase variant
        codex_dir = _ATHENAEUM_ROOT / f"Codex-God-{god_name}"
    if not codex_dir.exists():
        logger.debug("no codex dir for god %s, skipping skill write", god_name)
        return
    skills_dir = codex_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    for item in items:
        # Sanitize filename
        safe = re.sub(r"[^a-z0-9_-]+", "-", item.lower()).strip("-")
        if not safe:
            continue
        f = skills_dir / f"{safe}.md"
        f.write_text(
            f"# {item}\n\n"
            f"_Captured by Tier A+ extraction: {ts}_\n\n"
            f"## What\n\n"
            f"This skill was used in a session for god `{god_name}`.\n\n"
            f"## How\n\n"
            f"Auto-captured by `extract_llm_rich()` (B5). Edit this file "
            f"to add context, examples, and links.\n"
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_llm_rich(
    session_summary: str,
    god_name: str,
    *,
    dry_run: bool = False,
) -> Dict[str, List[str]]:
    """Opt-in LLM extraction for richer post-session learning.

    Behavior:
      - tier_a_plus=false (default) → returns empty result, no LLM call
      - tier_a_plus=true → one LLM call, parse, write to pantheon://, return

    Args:
        session_summary: Concise summary of the session (the post-session
            digest or compaction summary).
        god_name: Name of the god (e.g. "marvin", "thoth", "hephaestus").

    Returns:
        Dict with keys from RICH_FIELDS. Empty lists for any field the
        LLM didn't return.
    """
    if not _is_tier_a_plus_enabled(god_name):
        logger.debug("extract_llm_rich: tier_a_plus=false for %s, skipping",
                     god_name)
        return _empty_rich_result()

    provider = _resolve_llm_provider(god_name)
    if provider is None:
        logger.warning(
            "extract_llm_rich: tier_a_plus=true for %s but no LLM provider "
            "configured, skipping", god_name,
        )
        return _empty_rich_result()

    if not session_summary or not session_summary.strip():
        logger.debug("extract_llm_rich: empty session summary, skipping")
        return _empty_rich_result()

    prompt = _build_prompt(session_summary, god_name)
    if dry_run:
        return _empty_rich_result()

    try:
        raw = _call_llm(prompt, provider)
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, ValueError, json.JSONDecodeError) as e:
        logger.warning("extract_llm_rich: LLM call failed: %s", e)
        return _empty_rich_result()

    result = _parse_rich_response(raw)
    try:
        _write_to_pantheon(result, god_name)
    except sqlite3.Error as e:
        logger.warning("extract_llm_rich: pantheon write failed: %s", e)
    return result


# ---------------------------------------------------------------------------
# CLI for debugging
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    god = sys.argv[1] if len(sys.argv) > 1 else "marvin"
    summary = sys.argv[2] if len(sys.argv) > 2 else "Worked on a thing."
    result = extract_llm_rich(summary, god)
    print(json.dumps(result, indent=2))
