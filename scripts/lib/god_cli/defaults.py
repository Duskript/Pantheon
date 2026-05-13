"""
defaults.py — Sensible defaults, path resolution, and domain-to-codex mapping.

Responsibilities:
- get_default_model() -> str  — reads ~/.hermes/config.yaml
- get_default_provider() -> str
- get_author() -> str  — reads git config user.name
- get_home() -> str  — Hermes-aware home resolution (mirrors SDK)
- get_profiles_dir() -> Path
- get_codex_dir(name) -> Path
- get_bundled_codex_dir(codex_name) -> Path
- DOMAIN_CODEX_MAP — domain-to-codex mapping table
- suggest_bundled_codexes(domain) -> list[str]
- Path constants
"""

import os
import subprocess
from pathlib import Path

# ── Home Resolution (mirrors pantheon_sdk.py logic) ───────────────────

_HOME = os.path.expanduser("~")
_REAL_HOME = os.environ.get("HERMES_REAL_HOME", _HOME)
if _REAL_HOME != _HOME and _REAL_HOME != os.path.join(_HOME, ".."):
    _HOME = _REAL_HOME
if ".hermes/profiles" in _HOME:
    parts = _HOME.split("/.hermes/profiles/")
    _HOME = parts[0]

HOME = _HOME
PANTHEON_DIR = os.path.join(HOME, "pantheon")
ATHENAEUM_DIR = os.path.join(HOME, "athenaeum")
PROFILES_DIR = os.path.join(HOME, ".hermes", "profiles")
GODS_YAML_PATH = os.path.join(PANTHEON_DIR, "gods", "gods.yaml")
REGISTRY_PATH = os.path.join(PANTHEON_DIR, "pantheon-registry.yaml")
HERMES_CONFIG_PATH = os.path.join(HOME, ".hermes", "config.yaml")
HARNESSES_DIR = os.path.join(PANTHEON_DIR, "harnesses")
MESSAGES_DIR = os.path.join(PANTHEON_DIR, "gods", "messages")


def get_home() -> str:
    """Return the resolved home directory (Hermes-sandbox aware)."""
    return HOME


def get_profiles_dir() -> Path:
    """Return ~/.hermes/profiles/ as a Path."""
    return Path(PROFILES_DIR)


def get_profile_dir(name: str) -> Path:
    """Return ~/.hermes/profiles/{name}/ as a Path."""
    return get_profiles_dir() / name


def get_codex_dir(name: str) -> Path:
    """Return ~/athenaeum/Codex-God-{Name}/ as a Path.

    'name' should be the PascalCase display name (e.g. 'Asclepius').
    """
    return Path(ATHENAEUM_DIR) / f"Codex-God-{name}"


def get_bundled_codex_dir(codex_name: str) -> Path:
    """Return ~/athenaeum/{CodexName}/ as a Path.

    'codex_name' is the full Codex directory name (e.g. 'Codex-Apollo').
    """
    return Path(ATHENAEUM_DIR) / codex_name


# ── Default Value Helpers ─────────────────────────────────────────────


def get_default_model() -> str:
    """Read default model from ~/.hermes/config.yaml, fallback to 'deepseek-v4-flash'."""
    try:
        import yaml
        if os.path.isfile(HERMES_CONFIG_PATH):
            with open(HERMES_CONFIG_PATH) as f:
                cfg = yaml.safe_load(f) or {}
            model = cfg.get("model", {})
            if isinstance(model, dict) and "default" in model:
                return model["default"]
    except Exception:
        pass
    return "deepseek-v4-flash"


def get_default_provider() -> str:
    """Read default provider from ~/.hermes/config.yaml, fallback to 'opencode-go'."""
    try:
        import yaml
        if os.path.isfile(HERMES_CONFIG_PATH):
            with open(HERMES_CONFIG_PATH) as f:
                cfg = yaml.safe_load(f) or {}
            model = cfg.get("model", {})
            if isinstance(model, dict) and "provider" in model:
                return model["provider"]
    except Exception:
        pass
    return "opencode-go"


def get_author() -> str:
    """Read author name from git config, fallback to 'Konan'."""
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return "Konan"


def get_user() -> str:
    """Return the user's display name (always 'Konan' for now)."""
    return "Konan"


# ── Domain-to-Codex Mapping ───────────────────────────────────────────

DOMAIN_CODEX_MAP = {
    "creative": ["Codex-Apollo"],
    "health": ["Codex-Medica"],
    "forge": ["Codex-Forge"],
    "testing": ["Codex-Forge"],
    "code": ["Codex-Forge"],
    "engineering": ["Codex-Forge"],
}


def suggest_bundled_codexes(domain: str) -> list[str]:
    """Look up domain keywords in the mapping and return suggested Codexes.

    Uses substring matching: if any keyword from the user's domain description
    appears in a mapping's trigger key, that Codex is suggested.
    """
    domain_lower = domain.lower()
    suggested = []

    for trigger_key, codexes in DOMAIN_CODEX_MAP.items():
        if trigger_key in domain_lower:
            suggested.extend(codexes)
        # Also check for codex name substring match
        for codex in codexes:
            codename_lower = codex.lower()
            if codename_lower.replace("codex-", "") in domain_lower:
                suggested.append(codex)

    # Deduplicate while preserving order
    seen = set()
    return [cx for cx in suggested if not (cx in seen or seen.add(cx))]
