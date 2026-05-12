#!/usr/bin/env python3
"""
Pantheon Setup Server — handles the Welcome Wizard API during first-time setup.

Runs during initial install to:
  - Serve the welcome wizard (welcome.html)
  - Accept API key submissions and write them to .env
  - Check .env status

Started automatically by install-pantheon.sh on port 9876.
"""
import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

PANTHEON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PANTHEON_DIR, ".env")


class SetupHandler(SimpleHTTPRequestHandler):
    """HTTP handler that serves static files + setup API."""

    def __init__(self, *args, **kwargs):
        # Serve from pantheon repo root
        super().__init__(*args, directory=PANTHEON_DIR, **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/env/check":
            self._handle_check_env()
        elif path == "/api/env/models/recommend":
            self._handle_model_recommendations()
        else:
            # Serve static files (default behaviour)
            super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/env/key":
            self._handle_set_key()
        elif path == "/api/env/models/save":
            self._handle_save_models()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')

    def _handle_set_key(self):
        """Write an API key to .env."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)

            provider = data.get("provider", "").strip()
            api_key = data.get("api_key", "").strip()

            if not provider or not api_key:
                self._json(400, {"error": "provider and api_key are required"})
                return

            # Map provider names to env var names — covers all Hermes providers
            PROVIDER_ENV_MAP = {
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

            env_var = PROVIDER_ENV_MAP.get(provider)
            if not env_var:
                self._json(400, {"error": f"unknown provider: {provider}"})
                return

            # Read existing .env or start fresh
            env_lines = []
            if os.path.isfile(ENV_PATH):
                with open(ENV_PATH) as f:
                    env_lines = f.readlines()

            # Find and replace, or append
            found = False
            for i, line in enumerate(env_lines):
                stripped = line.strip()
                if stripped.startswith(f"{env_var}="):
                    env_lines[i] = f"{env_var}={api_key}\n"
                    found = True
                    break
                # Also handle commented-out versions
                if stripped.startswith(f"# {env_var}=") or stripped.startswith(f"#{env_var}="):
                    env_lines[i] = f"{env_var}={api_key}\n"
                    found = True
                    break

            if not found:
                env_lines.append(f"\n{env_var}={api_key}\n")

            # Write back
            with open(ENV_PATH, "w") as f:
                f.writelines(env_lines)

            self._json(200, {
                "status": "ok",
                "message": f"{provider} API key saved to .env",
                "provider": provider,
                "env_var": env_var,
            })

        except (json.JSONDecodeError, OSError) as e:
            self._json(500, {"error": str(e)})

    def _handle_check_env(self):
        """Return which providers have keys configured."""
        configured = {}
        if os.path.isfile(ENV_PATH):
            with open(ENV_PATH) as f:
                for line in f:
                    stripped = line.strip()
                    if "=" in stripped and not stripped.startswith("#"):
                        key, _, value = stripped.partition("=")
                        if value and not value.startswith("$") and not value.startswith("your_"):
                            configured[key] = "set" if len(value) > 4 else "empty"

        self._json(200, {
            "status": "ok",
            "env_exists": os.path.isfile(ENV_PATH),
            "configured": configured,
        })

    MODEL_RECOMMENDATIONS = {
        "opencode-go": {
            "label": "OpenCode Go",
            "models": {
                "chat": {
                    "default": "deepseek-v4-flash",
                    "options": ["deepseek-v4-flash", "kimi-k2.5", "minimax-m2.5", "deepseek-v4-pro"],
                    "note": "Recommended: deepseek-v4-flash — fast, capable, great value"
                },
                "extraction": {
                    "default": "minimax-m2.5",
                    "options": ["minimax-m2.5", "deepseek-v4-flash", "kimi-k2.5"],
                    "note": "Recommended: minimax-m2.5 — best entity extraction accuracy"
                },
                "extraction_fallback": {
                    "default": "deepseek-v4-flash",
                    "options": ["deepseek-v4-flash", "minimax-m2.5"],
                    "note": "Fallback if primary extraction model fails"
                },
                "vision": {
                    "default": "",
                    "options": [],
                    "note": "Vision uses OpenRouter or configured provider"
                },
            },
            "auto_configure": True,
        },
        "openrouter": {
            "label": "OpenRouter",
            "models": {
                "chat": {
                    "default": "deepseek/deepseek-v4-flash",
                    "options": [
                        "deepseek/deepseek-v4-flash",
                        "google/gemini-2.5-pro-preview-03-25",
                        "anthropic/claude-sonnet-4",
                        "openai/gpt-4o",
                    ],
                    "note": "Great all-rounders — pick your preferred family"
                },
                "extraction": {
                    "default": "google/gemini-2.5-flash-preview",
                    "options": ["google/gemini-2.5-flash-preview", "deepseek/deepseek-v4-flash", "openai/gpt-4o-mini"],
                    "note": "Gemini Flash offers excellent extraction at low cost"
                },
                "extraction_fallback": {
                    "default": "deepseek/deepseek-v4-flash",
                    "options": ["deepseek/deepseek-v4-flash", "openai/gpt-4o-mini"],
                    "note": "Fallback if primary extraction model fails"
                },
                "vision": {
                    "default": "google/gemini-2.5-pro-preview-03-25",
                    "options": ["google/gemini-2.5-pro-preview-03-25", "anthropic/claude-sonnet-4", "openai/gpt-4o"],
                    "note": "Best vision performance: Gemini 2.5 Pro"
                },
            },
            "auto_configure": False,
        },
        "ollama": {
            "label": "Ollama (Local)",
            "models": {
                "chat": {
                    "default": "llama3.3",
                    "options": ["llama3.3", "qwen2.5", "mistral", "phi-4"],
                    "note": "llama3.3 is the best local all-rounder"
                },
                "extraction": {
                    "default": "llama3.3",
                    "options": ["llama3.3", "mistral", "qwen2.5"],
                    "note": "Use the same model — local extraction works fine"
                },
                "extraction_fallback": {
                    "default": "llama3.3",
                    "options": ["llama3.3", "mistral"],
                    "note": "Same local model as fallback"
                },
                "vision": {
                    "default": "llama3.2-vision",
                    "options": ["llama3.2-vision", "llava"],
                    "note": "Requires a vision-capable local model"
                },
            },
            "auto_configure": False,
        },
        "ollama-cloud": {
            "label": "Ollama Cloud",
            "models": {
                "chat": {
                    "default": "deepseek-v4-flash:cloud",
                    "options": ["deepseek-v4-flash:cloud", "gemma4:31b-cloud", "kimi-k2.6:cloud"],
                    "note": "deepseek-v4-flash:cloud — fast and capable"
                },
                "extraction": {
                    "default": "minimax-m2.5",
                    "options": ["minimax-m2.5", "deepseek-v4-flash:cloud"],
                    "note": "Use minimax-m2.5 via OpenRouter for extraction"
                },
                "extraction_fallback": {
                    "default": "deepseek-v4-flash:cloud",
                    "options": ["deepseek-v4-flash:cloud"],
                    "note": "Fallback via Ollama Cloud"
                },
                "vision": {
                    "default": "gemma4:31b-cloud",
                    "options": ["gemma4:31b-cloud", "kimi-k2.6:cloud"],
                    "note": "Gemma 4 has solid vision capabilities"
                },
            },
            "auto_configure": False,
        },
    }

    COMMON_RECOMMENDATIONS = {
        "embedding": {
            "default": "nvidia/llama-nemotron-embed-vl-1b-v2:free",
            "provider": "openrouter",
            "note": "Embeddings always route through OpenRouter — free model, no key needed if you have any OpenRouter-compatible key",
        },
        "summary": {
            "default": "google/gemini-3-flash-preview",
            "provider": "openrouter",
            "note": "Used for context compression — lightweight, fast, excellent summaries",
        },
    }

    def _handle_model_recommendations(self):
        """Return model recommendations based on configured providers."""
        configured = {}
        if os.path.isfile(ENV_PATH):
            with open(ENV_PATH) as f:
                for line in f:
                    stripped = line.strip()
                    if "=" in stripped and not stripped.startswith("#"):
                        key, _, value = stripped.partition("=")
                        if value and not value.startswith("$") and not value.startswith("your_"):
                            configured[key] = "set" if len(value) > 4 else "empty"

        # Determine primary provider
        primary_provider = None
        has_ollama_key = "OLLAMA_API_KEY" in configured
        has_ollama_url = configured.get("OLLAMA_BASE_URL", "").strip() != ""

        provider_keys = {
            "OPENCODE_GO_API_KEY": "opencode-go",
            "OPENROUTER_API_KEY": "openrouter",
            "OPENAI_API_KEY": "openai",
            "ANTHROPIC_API_KEY": "anthropic",
            "GOOGLE_API_KEY": "google-gemini",
        }

        if has_ollama_key and has_ollama_url:
            provider_keys["OLLAMA_API_KEY"] = "ollama-cloud"
        elif has_ollama_key:
            provider_keys["OLLAMA_API_KEY"] = "ollama"

        for env_var, provider_id in provider_keys.items():
            if env_var in configured:
                primary_provider = provider_id
                break

        recommendations = {}
        if primary_provider and primary_provider in self.MODEL_RECOMMENDATIONS:
            recommendations = self.MODEL_RECOMMENDATIONS[primary_provider]

        # Always include common recommendations (embedding + summary)
        recommendations["common"] = self.COMMON_RECOMMENDATIONS

        self._json(200, {
            "status": "ok",
            "primary_provider": primary_provider,
            "recommendations": recommendations,
        })

    def _handle_save_models(self):
        """Save model configuration to .env."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)

            models = data.get("models", {})

            # Map model roles to env vars
            MODEL_ENV_MAP = {
                "extraction": "ATHENAEUM_EXTRACT_MODEL",
                "extraction_fallback": "ATHENAEUM_EXTRACT_MODEL_FALLBACK",
            }

            env_lines = []
            if os.path.isfile(ENV_PATH):
                with open(ENV_PATH) as f:
                    env_lines = f.readlines()

            for role, model_name in models.items():
                env_var = MODEL_ENV_MAP.get(role)
                if not env_var:
                    continue
                if not model_name:
                    continue

                found = False
                for i, line in enumerate(env_lines):
                    stripped = line.strip()
                    if stripped.startswith(f"{env_var}=") or stripped.startswith(f"# {env_var}=") or stripped.startswith(f"#{env_var}="):
                        env_lines[i] = f"{env_var}={model_name}\n"
                        found = True
                        break

                if not found:
                    env_lines.append(f"{env_var}={model_name}\n")

            with open(ENV_PATH, "w") as f:
                f.writelines(env_lines)

            self._json(200, {
                "status": "ok",
                "message": "Model configuration saved to .env",
            })

        except (json.JSONDecodeError, OSError) as e:
            self._json(500, {"error": str(e)})

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        sys.stderr.write(f"[setup-server] {args[0]} {args[1]} {args[2]}\n")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9876
    server = HTTPServer(("127.0.0.1", port), SetupHandler)
    print(f"Pantheon Setup Server running on http://127.0.0.1:{port}")
    print(f"Open http://127.0.0.1:{port}/welcome.html to start")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
