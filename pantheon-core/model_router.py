"""Model Router — automatic free model selection for Pantheon tasks.

Ships with Pantheon Core so every deployment auto-picks the best free
OpenRouter model for the task, with zero config needed.

Policy:
  - Always prefer free models (prompt_cost == 0)
  - Pick the strongest serving model appropriate for the task type
  - Fall back gracefully if the best pick is down
  - Env var overrides take priority when set

Usage:
    from model_router import get_best_free_model

    model = get_best_free_model("extraction")
    # → "google/gemma-4-26b-a4b-it:free" (or whatever is best today)
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("model_router")

# ── Task profiles ──────────────────────────────────────────────────────
# Each task type defines what the model needs to be good at.
# The router uses this to rank candidates.

TASK_PROFILES = {
    "extraction": {
        "label": "Entity & relation extraction from text",
        "min_params": 1_000_000_000,       # 1B minimum
        "prefer_json_mode": True,
        "prefer_instruction": True,
        "keywords": ["instruct", "it"],     # instruction-tuned variants
    },
    "embedding": {
        "label": "Text embedding generation",
        "min_params": 0,                   # any embedding model works
        "prefer_json_mode": False,
        "prefer_instruction": False,
        "keywords": ["embed"],
    },
    "chat": {
        "label": "General chat / assistant",
        "min_params": 3_000_000_000,       # 3B minimum for decent quality
        "prefer_json_mode": False,
        "prefer_instruction": True,
        "keywords": ["instruct", "it"],
    },
    "reasoning": {
        "label": "Multi-step reasoning / analysis",
        "min_params": 7_000_000_000,       # 7B minimum for reasoning
        "prefer_json_mode": False,
        "prefer_instruction": True,
        "keywords": ["reason", "think", "instruct"],
    },
}

# ── Env var overrides ──────────────────────────────────────────────────
# If set, these take priority over dynamic selection.
# Format: ATHENAEUM_{TASK}_MODEL or PANTHEON_{TASK}_MODEL

ENV_OVERRIDES = {
    "extraction": ("ATHENAEUM_EXTRACT_MODEL", "PANTHEON_EXTRACT_MODEL"),
    "embedding": ("ATHENAEUM_EMBED_MODEL", "PANTHEON_EMBED_MODEL"),
    "chat": ("PANTHEON_CHAT_MODEL",),
    "reasoning": ("PANTHEON_REASONING_MODEL",),
}


# ── Model cache ────────────────────────────────────────────────────────
# Free models change infrequently, so cache for 1 hour.

_cache: Dict[str, Tuple[float, List[Dict]]] = {}  # task -> (timestamp, models)
CACHE_TTL = 3600  # 1 hour


# ── Fallback defaults (hardcoded safety net) ───────────────────────────
# If OpenRouter API is unreachable, use these tested-working defaults.

FALLBACK_MODELS = {
    "extraction": "google/gemma-4-26b-a4b-it:free",
    "embedding": "nvidia/llama-nemotron-embed-vl-1b-v2:free",
    "chat": "google/gemma-4-26b-a4b-it:free",
    "reasoning": "google/gemma-4-26b-a4b-it:free",
}


# ── API helpers ────────────────────────────────────────────────────────

def _get_api_key() -> str:
    """Get OpenRouter API key from environment."""
    return os.environ.get("OPENROUTER_API_KEY", "")


def _fetch_free_models() -> List[Dict]:
    """Fetch all free models from OpenRouter's API.

    Returns list of model dicts with prompt_cost == 0.
    Returns empty list on failure (caller falls back to hardcoded defaults).
    """
    api_key = _get_api_key()
    if not api_key:
        logger.warning("OPENROUTER_API_KEY not set — cannot fetch free models")
        return []

    try:
        import httpx

        resp = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        free_models = []
        for m in data.get("data", []):
            pricing = m.get("pricing", {})
            prompt_cost = float(pricing.get("prompt", 1))
            completion_cost = float(pricing.get("completion", 1))
            if prompt_cost == 0 and completion_cost == 0:
                free_models.append(m)

        logger.debug("Found %d free models on OpenRouter", len(free_models))
        return free_models

    except Exception as exc:
        logger.warning("Failed to fetch free models from OpenRouter: %s", exc)
        return []


def _estimate_params(model_id: str) -> int:
    """Estimate parameter count from model ID.

    Many OpenRouter models include param counts in their ID
    (e.g. 'llama-3.1-8b-instruct' → 8B, 'gemma-4-26b-a4b-it' → 26B).
    Falls back to 0 if unknown.
    """
    import re

    # Match patterns like 8b, 26b-a4b, 70b, 1.2b, 405b
    match = re.search(r'(\d+)[bB]', model_id)
    if match:
        return int(match.group(1)) * 1_000_000_000

    match = re.search(r'(\d+\.\d+)[bB]', model_id)
    if match:
        return int(float(match.group(1)) * 1_000_000_000)

    return 0


def _rank_for_task(models: List[Dict], task: str) -> List[Dict]:
    """Rank free models by suitability for the given task type.

    Uses the TASK_PROFILES to score each model. Higher score = better fit.
    """
    profile = TASK_PROFILES.get(task, TASK_PROFILES["chat"])
    scored = []

    for m in models:
        mid = m.get("id", "")
        name = m.get("name", "").lower()
        full_text = f"{mid} {name}".lower()

        score = 0
        params = _estimate_params(mid)

        # Parameter bonus — bigger models score higher for most tasks
        min_params = profile.get("min_params", 0)
        if params >= min_params and params > 0:
            # Log-scale: 8B → ~9, 26B → ~10.4, 70B → ~11.1
            score += min(15, (params / 1_000_000_000) ** 0.4)

        # Instruction-tuned bonus
        if profile.get("prefer_instruction"):
            for kw in profile.get("keywords", []):
                if kw.lower() in full_text:
                    score += 3
                    break

        # Small penalty for vision models (heavier, not needed for text tasks)
        if "vision" in full_text or "vl" in full_text:
            score -= 2

        scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for score, m in scored if score > 0]


def _check_model_serving(model_id: str) -> bool:
    """Quick-check if a model is actually serving by making a tiny request.

    Some free models are listed but return provider errors.
    This does a 2-token test to verify it serves.
    """
    api_key = _get_api_key()
    if not api_key:
        return False

    try:
        import httpx

        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": "OK"}],
                "max_tokens": 2,
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ── Public API ─────────────────────────────────────────────────────────

def get_best_free_model(task: str = "extraction") -> str:
    """Get the best free OpenRouter model for the given task type.

    Priority:
      1. Env var override (if set)
      2. Dynamic selection from OpenRouter's free models list
      3. Hardcoded fallback

    Args:
        task: One of 'extraction', 'embedding', 'chat', 'reasoning'

    Returns:
        Model ID string (e.g. 'google/gemma-4-26b-a4b-it:free')
    """
    # 1. Env var override
    for env_var in ENV_OVERRIDES.get(task, ()):
        override = os.environ.get(env_var, "").strip()
        if override:
            logger.info("Using env override %s=%s", env_var, override)
            return override

    # 2. Dynamic selection
    models = _fetch_free_models()
    if models:
        ranked = _rank_for_task(models, task)
        if ranked:
            best = ranked[0]
            best_id = best.get("id", "")

            # Quick serving check — if the best model is down, try next
            for candidate in ranked[:5]:  # try top 5
                cid = candidate.get("id", "")
                if _check_model_serving(cid):
                    logger.info("Selected free model %s for task '%s'", cid, task)
                    return cid

            logger.warning(
                "Top 5 free models all failed serving check, using top-ranked: %s",
                best_id,
            )
            return best_id

    # 3. Hardcoded fallback
    fallback = FALLBACK_MODELS.get(task, "")
    logger.info("Using fallback model %s for task '%s'", fallback, task)
    return fallback


def check_override(task: str) -> Optional[str]:
    """Check if an env var override exists for this task, without dynamic lookup.

    Useful for scripts that want to respect manual config without
    hitting the OpenRouter API.
    """
    for env_var in ENV_OVERRIDES.get(task, ()):
        override = os.environ.get(env_var, "").strip()
        if override:
            return override
    return None
