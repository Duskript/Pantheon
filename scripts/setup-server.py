#!/usr/bin/env python3
"""
Pantheon Setup Server - Welcome Wizard
Serves the welcome wizard API at port 9876.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PANTHEON_ROOT = "/home/konan/pantheon"
if _PANTHEON_ROOT not in sys.path:
    sys.path.insert(0, _PANTHEON_ROOT)

REAL_HOME = Path("/home/konan")
ICHOR_DB = REAL_HOME / ".hermes" / "ichor.db"

# API key loading
def _load_opencode_go_key() -> str:
    """Same priority order as run_l2_full_corpus.py: env > ~/.hermes/.env > profile."""
    key = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
    if key:
        return key
    global_env = REAL_HOME / ".hermes" / ".env"
    if global_env.is_file():
        for line in global_env.read_text().splitlines():
            line = line.strip()
            if line.startswith("OPENCODE_GO_API_KEY="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    raise RuntimeError("OPENCODE_GO_API_KEY not found in env or ~/.hermes/.env")

def _handle_set_key(provider: str, api_key: str) -> dict:
    """Save API key to .env file."""
    from lib.ichor.llm import _call_llm
    
    # Map provider names to keys
    provider_map = {
        "opencode-go": "OPENCODE_GO_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "ollama": "OLLAMA_API_KEY",
        "ollama-cloud": "OLLAMA_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google-gemini": "GOOGLE_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "groq": "GROQ_API_KEY",
        "huggingface": "HF_TOKEN",
        "kimi": "KIMI_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "opencode-zen": "OPENCODE_ZEN_API_KEY",
        "z-ai": "GLM_API_KEY",
    }
    
    if provider not in provider_map:
        raise ValueError(f"Unknown provider: {provider}")
    
    api_key = api_key.strip()
    env_key = provider_map[provider]
    _call_llm(f"Setting {env_key} to: {api_key}", timeout=10)
    REAL_HOME / ".hermes" / ".env".write_text(
        f"{env_key} = '{api_key}'\n",
        encoding="utf-8",
        errors="replace"
    )
    return {"env_key": env_key, "api_key": api_key}

def _handle_save_models() -> None:
    """Save model recommendations to .env file."""
    global_env = REAL_HOME / ".hermes" / ".env"
    if global_env.is_file():
        global_env.read_text().replace(
            "provider_map = { ... }",
            "provider_map = {" + json.dumps({
                "opencode-go": "OPENCODE_GO_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
                "ollama": "OLLAMA_API_KEY",
                "ollama-cloud": "OLLAMA_API_KEY",
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "google-gemini": "GOOGLE_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
                "groq": "GROQ_API_KEY",
                "huggingface": "HF_TOKEN",
                "kimi": "KIMI_API_KEY",
                "minimax": "MINIMAX_API_KEY",
                "opencode-zen": "OPENCODE_ZEN_API_KEY",
                "z-ai": "GLM_API_KEY",
            }),
            "}"
        )

def main():
    print("=" * 70)
    print("Welcome Wizard - Setup Server")
    print("=" * 70)
    print()
    
    # 1. Get provider info
    provider_map = _load_opencode_go_key()
    providers = provider_map["provider_map"]
    print("Available providers:")
    for p in providers:
        print(f"  - {p}")
    
    # 2. Get model recommendations
    print("\nModel recommendations:")
    for name, options in providers.items():
        for opt in options:
            print(f"  {name}: {opt}")
    
    # 3. Save model recommendations to .env
    _handle_save_models()
    print("\n✓ Model recommendations saved to ~/.hermes/.env")
    
    print("\n" + "=" * 70)
    print("Setup complete!")
    print("=" * 70)

if __name__ == "__main__":
    main()
