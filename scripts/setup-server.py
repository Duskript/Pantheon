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
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

PANTHEON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PANTHEON_DIR, ".env")

# ── Launch state (thread-safe) ──────────────────────────────────────────────
_launch_step: str = "idle"  # idle | installing_gods | starting_gateway | waiting | done | error
_launch_msg: str = ""
_launch_error: str | None = None
_launch_lock = threading.Lock()
_launch_thread: threading.Thread | None = None


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
        elif path == "/api/env/ollama-status":
            self._handle_ollama_status()
        elif path == "/api/launch/status":
            self._handle_launch_status()
        else:
            # Serve static files (default behaviour)
            super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/env/key":
            self._handle_set_key()
        elif path == "/api/env/models/save":
            self._handle_save_models()
        elif path == "/api/env/embed-key":
            self._handle_set_embed_key()
        elif path == "/api/launch":
            self._handle_launch()
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
        """Return which providers have keys configured, including embedding."""
        configured = {}
        if os.path.isfile(ENV_PATH):
            with open(ENV_PATH) as f:
                for line in f:
                    stripped = line.strip()
                    if "=" in stripped and not stripped.startswith("#"):
                        key, _, value = stripped.partition("=")
                        if value and not value.startswith("$") and not value.startswith("your_"):
                            configured[key] = "set" if len(value) > 4 else "empty"

        # Detect embedding provider status
        embed_provider = configured.get("ATHENAEUM_EMBED_PROVIDER", "")
        has_embed_key = bool(
            configured.get("ATHENAEUM_EMBED_API_KEY")
            or configured.get("OPENROUTER_API_KEY")
        )
        embed_configured = bool(embed_provider and has_embed_key)

        self._json(200, {
            "status": "ok",
            "env_exists": os.path.isfile(ENV_PATH),
            "configured": configured,
            "embedding": {
                "configured": embed_configured,
                "provider": embed_provider or None,
                "has_key": has_embed_key,
            },
        })

    EMBED_PROVIDER_MAP = {
        "openrouter": {
            "env_var": "OPENROUTER_API_KEY",
            "model": "nvidia/llama-nemotron-embed-vl-1b-v2:free",
            "url": "https://openrouter.ai/api/v1/embeddings",
            "label": "OpenRouter",
            "note": "Free model, no extra cost — uses your OpenRouter key",
        },
        "jina": {
            "env_var": "JINA_API_KEY",
            "model": "jina-embeddings-v3",
            "url": "https://api.jina.ai/v1/embeddings",
            "label": "Jina AI",
            "note": "$0.01/1M tokens — first 1M free, 1024-dim",
        },
        "voyage": {
            "env_var": "VOYAGE_API_KEY",
            "model": "voyage-lite-02-instruct",
            "url": "https://api.voyageai.com/v1/embeddings",
            "label": "Voyage AI",
            "note": "$0.01/1M tokens — 1024-dim, instruct-tuned",
        },
        "ollama": {
            "env_var": "OLLAMA_API_KEY",
            "model": "nomic-embed-text",
            "url": "http://localhost:11434/api/embeddings",
            "label": "Ollama (local)",
            "note": "Free, offline — requires Ollama installed + model pulled",
        },
    }

    def _handle_ollama_status(self):
        """Check if Ollama is installed and/or running."""
        result = {"installed": False, "running": False, "version": None}
        try:
            import subprocess
            r = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                result["installed"] = True
                result["version"] = r.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        if result["installed"]:
            try:
                import httpx
                resp = httpx.get("http://localhost:11434/api/tags", timeout=3)
                if resp.status_code == 200:
                    result["running"] = True
                    models = resp.json().get("models", [])
                    embed_models = [m["name"] for m in models if "embed" in m["name"].lower() or "nomic" in m["name"].lower() or "bge" in m["name"].lower()]
                    result["embed_models"] = embed_models
            except Exception:
                pass

        self._json(200, {"status": "ok", "ollama": result})

    def _handle_set_embed_key(self):
        """Save an embedding provider configuration to .env."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)

            provider = data.get("provider", "").strip().lower()
            api_key = data.get("api_key", "").strip()
            model_override = data.get("model", "").strip()

            if not provider or provider not in self.EMBED_PROVIDER_MAP:
                self._json(400, {"error": f"unknown or missing embedding provider: {provider}"})
                return

            cfg = self.EMBED_PROVIDER_MAP[provider]
            env_lines = []
            if os.path.isfile(ENV_PATH):
                with open(ENV_PATH) as f:
                    env_lines = f.readlines()

            def _upsert(key_name, value, ensure_newline=True):
                nonlocal env_lines
                found = False
                for i, line in enumerate(env_lines):
                    stripped = line.strip()
                    if stripped.startswith(f"{key_name}=") or stripped.startswith(f"# {key_name}=") or stripped.startswith(f"#{key_name}="):
                        env_lines[i] = f"{key_name}={value}\n"
                        found = True
                        break
                if not found:
                    nl = "\n" if ensure_newline and env_lines and not env_lines[-1].endswith("\n") else ""
                    env_lines.append(f"{nl}{key_name}={value}\n")

            # Save embedding provider identity
            _upsert("ATHENAEUM_EMBED_PROVIDER", provider)

            # Save the API key (general + provider-specific)
            if api_key:
                _upsert("ATHENAEUM_EMBED_API_KEY", api_key)
                _upsert(cfg["env_var"], api_key)

            # Save the model (allow override, else use default)
            model = model_override or cfg["model"]
            _upsert("ATHENAEUM_EMBED_MODEL", model)

            # Save the URL
            _upsert("ATHENAEUM_EMBED_URL", cfg["url"])

            with open(ENV_PATH, "w") as f:
                f.writelines(env_lines)

            self._json(200, {
                "status": "ok",
                "message": f"{cfg['label']} configured for embeddings",
                "provider": provider,
                "model": model,
            })

        except (json.JSONDecodeError, OSError) as e:
            self._json(500, {"error": str(e)})

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

        # Detect current embedding provider
        embed_provider_name = configured.get("ATHENAEUM_EMBED_PROVIDER", "")
        embed_provider_info = None
        if embed_provider_name and embed_provider_name in self.EMBED_PROVIDER_MAP:
            cfg = self.EMBED_PROVIDER_MAP[embed_provider_name]
            embed_provider_info = {
                "label": cfg["label"],
                "model": configured.get("ATHENAEUM_EMBED_MODEL", cfg["model"]),
                "note": cfg["note"],
            }
        elif configured.get("OPENROUTER_API_KEY"):
            # OpenRouter key exists but no explicit embed provider — auto-detect
            embed_provider_info = {
                "label": "OpenRouter (auto)",
                "model": configured.get("ATHENAEUM_EMBED_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2:free"),
                "note": "Free embedding model via OpenRouter key",
            }

        # Always include common recommendations
        recommendations["common"] = self.COMMON_RECOMMENDATIONS
        recommendations["embedding_providers"] = {
            name: {
                "label": cfg["label"],
                "model": cfg["model"],
                "note": cfg["note"],
            }
            for name, cfg in self.EMBED_PROVIDER_MAP.items()
        }

        self._json(200, {
            "status": "ok",
            "primary_provider": primary_provider,
            "recommendations": recommendations,
            "embedding": {
                "configured": embed_provider_info is not None,
                "current": embed_provider_info,
            },
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

    # ── Launch handlers ─────────────────────────────────────────────────────

    def _handle_launch(self):
        """Start Pantheon launch in background thread."""
        global _launch_step, _launch_msg, _launch_thread

        with _launch_lock:
            if _launch_step in ("installing_gods", "starting_gateway", "waiting"):
                self._json(200, {"status": "already_launching", "step": _launch_step})
                return
            _launch_step = "installing_gods"
            _launch_msg = "Installing core gods..."
            _launch_error = None

        _launch_thread = threading.Thread(target=_launch_worker, daemon=True)
        _launch_thread.start()
        self._json(200, {"status": "launching", "step": "installing_gods"})

    def _handle_launch_status(self):
        """Return current launch progress."""
        with _launch_lock:
            self._json(200, {
                "status": "ok",
                "step": _launch_step,
                "message": _launch_msg,
                "error": _launch_error,
            })

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


# ── Background launch worker ────────────────────────────────────────────────

def _launch_worker():
    """Run launch steps in background, updating global state."""
    global _launch_step, _launch_msg, _launch_error
    import httpx  # noqa: PLC0415
    try:
        # Step 1: Install core gods
        with _launch_lock:
            _launch_step = "installing_gods"
            _launch_msg = "Installing Hermes + Hephaestus..."
        subprocess.run(
            [sys.executable, "scripts/pantheon-install", "."],
            cwd=PANTHEON_DIR,
            capture_output=True, text=True, timeout=60,
        )

        # Step 2: Initialize Athenaeum (create Codex directories)
        with _launch_lock:
            _launch_step = "initializing_athenaeum"
            _launch_msg = "Creating Athenaeum knowledge store..."
        subprocess.run(
            ["bash", "scripts/init-athenaeum.sh"],
            cwd=PANTHEON_DIR,
            capture_output=True, text=True, timeout=30,
        )

        # Step 3: Start Pantheon MCP server (port 8010)
        with _launch_lock:
            _launch_step = "starting_mcp"
            _launch_msg = "Starting Pantheon MCP server..."
        # Kill any previous MCP server
        subprocess.run(["pkill", "-f", "mcp_server.py"], capture_output=True, timeout=5)
        time.sleep(0.5)
        mcp_log = "/tmp/pantheon-mcp.log"
        with open(mcp_log, "w") as f:
            subprocess.Popen(
                [sys.executable, "pantheon-core/mcp_server.py", "--port", "8010"],
                cwd=PANTHEON_DIR,
                stdout=f, stderr=subprocess.STDOUT,
            )

        # Step 4: Start Hermes gateway
        with _launch_lock:
            _launch_step = "starting_gateway"
            _launch_msg = "Starting Pantheon gateway..."
        subprocess.run(["pkill", "-f", "hermes.*gateway"], capture_output=True, timeout=5)
        time.sleep(0.5)
        gateway_log = "/tmp/pantheon-gateway.log"
        with open(gateway_log, "w") as f:
            subprocess.Popen(
                ["hermes", "gateway"],
                stdout=f, stderr=subprocess.STDOUT,
            )

        # Step 5: Wait for both MCP (8010) and Web UI (8787)
        with _launch_lock:
            _launch_step = "waiting"
            _launch_msg = "Waiting for services to become ready..."

        mcp_ready = False
        web_ready = False
        for _ in range(30):  # up to ~60s
            time.sleep(2)
            if not mcp_ready:
                try:
                    resp = httpx.get("http://localhost:8010/health", timeout=2)
                    if resp.status_code < 500:
                        mcp_ready = True
                except Exception:
                    # Also try the MCP endpoint directly
                    try:
                        resp = httpx.get("http://localhost:8010/mcp", timeout=2)
                        mcp_ready = True
                    except Exception:
                        pass
            if not web_ready:
                try:
                    resp = httpx.get("http://localhost:8787", timeout=2)
                    if resp.status_code < 500:
                        web_ready = True
                except Exception:
                    pass
            if mcp_ready and web_ready:
                with _launch_lock:
                    _launch_step = "done"
                    _launch_msg = "Pantheon is running!"
                return

        # Partial success — at least one service is up
        if mcp_ready or web_ready:
            with _launch_lock:
                _launch_step = "done"
                parts = []
                if web_ready: parts.append("Web UI")
                if mcp_ready: parts.append("MCP")
                _launch_msg = f"{' + '.join(parts)} running — finishing startup"
        else:
            with _launch_lock:
                _launch_step = "done"
                _launch_msg = "Services started — may take a moment to be ready"

    except Exception as exc:
        with _launch_lock:
            _launch_step = "error"
            _launch_msg = f"Launch failed: {exc}"
            _launch_error = str(exc)


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
