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

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/env/key":
            self._handle_set_key()
        elif path == "/api/env/check":
            self._handle_check_env()
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
