"""Pantheon Standard Path Resolver — map artifact types to canonical filesystem paths.

Usage (standalone test):
    python3 -c "from lib.pantheon_path import resolve_path; \\
        print(resolve_path('upgrade', name='conductor-mcp-step-execution'))"

Usage (MCP tool):
    @mcp.tool()
    async def pantheon_path(type, name, god, category, date, create):
        return resolve_path(type=type, name=name, god=god,
                            category=category, date=date, create=create)
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

_REAL_HOME = os.path.expanduser("~")
# Guard against Hermes profile home stub (e.g. ~/.hermes/profiles/thoth/home/)
# Resolve up to the real home directory by climbing up from the stub.
if ".hermes/profiles" in _REAL_HOME:
    parts = _REAL_HOME.split(os.sep)
    # Find the index of '.hermes' and go one level above it
    try:
        idx = parts.index(".hermes")
        _REAL_HOME = os.sep.join(parts[:idx])
    except ValueError:
        pass
_PANTHEON = Path(_REAL_HOME) / "pantheon"
_ATHENAEUM = Path(_REAL_HOME) / "athenaeum"
_HERMES = Path(_REAL_HOME) / ".hermes"

# ---------------------------------------------------------------------------
# Type registry
# ---------------------------------------------------------------------------

_REGISTRY = {}


def _register(type_name, fn, needs_god=False, needs_name=True):
    _REGISTRY[type_name] = (fn, needs_god, needs_name)


def resolve_path(
    type: str,
    name: str = "",
    god: str = "",
    category: str = "",
    date: str = "",
    create: bool = False,
) -> dict:
    """Resolve a canonical Pantheon path for any artifact type.

    Returns dict with keys: path, exists, created, index, url, error.
    """
    type = type.lower()

    if type not in _REGISTRY:
        valid = sorted(_REGISTRY.keys())
        return {
            "path": None,
            "exists": False,
            "created": False,
            "index": None,
            "url": None,
            "error": f"Unknown type: '{type}'. Valid: {', '.join(valid)}",
        }

    fn, needs_god, needs_name = _REGISTRY[type]

    if needs_god and not god:
        return {
            "path": None,
            "exists": False,
            "created": False,
            "index": None,
            "url": None,
            "error": f"Type '{type}' requires 'god' parameter",
        }

    if needs_name and not name:
        return {
            "path": None,
            "exists": False,
            "created": False,
            "index": None,
            "url": None,
            "error": f"Type '{type}' requires 'name' parameter",
        }

    try:
        path = fn(name=name, god=god, category=category, date=date)
    except ValueError as e:
        return {
            "path": None,
            "exists": False,
            "created": False,
            "index": None,
            "url": None,
            "error": str(e),
        }

    exists = path.exists()
    created = False
    index = _resolve_index(path, type)

    if create and not exists:
        # Directory-type paths (no suffix) need mkdir on the path itself.
        # File-type paths (with .md, .py, etc.) need mkdir on the parent.
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
        exists = path.exists()
        created = exists

    return {
        "path": str(path.expanduser().resolve()),
        "exists": exists,
        "created": created,
        "index": str(index.expanduser().resolve()) if index else None,
        "url": None,
        "error": None,
    }


def _resolve_index(path: Path, type: str) -> Optional[Path]:
    """Find the INDEX.md that should contain this artifact, if any."""
    plans_indices = {
        "plans/upgrades",
        "plans/features",
        "plans/tools",
        "plans/ideas",
    }
    for keyword in plans_indices:
        if keyword in str(path):
            return _PANTHEON / keyword / "INDEX.md"
    if "project-ideas" in str(path):
        return _PANTHEON / "project-ideas" / "INDEX.md"
    if "shared/decisions" in str(path):
        return _PANTHEON / "shared" / "decisions" / "INDEX.md"
    if "reports" in str(path) and "Codex" in str(path):
        parent = path.parent if path.suffix else path
        return parent / "INDEX.md"
    return None


# ---------------------------------------------------------------------------
# Per-type path resolvers
# ---------------------------------------------------------------------------


def _upgrade(name: str, **kw) -> Path:
    return _PANTHEON / "plans" / "upgrades" / name


def _feature(name: str, **kw) -> Path:
    return _PANTHEON / "plans" / "features" / name


def _idea(name: str, **kw) -> Path:
    return _PANTHEON / "plans" / "ideas" / f"{name}.md"


def _project_idea(name: str, **kw) -> Path:
    return _PANTHEON / "project-ideas" / f"{name}.md"


def _tool_spec(name: str, **kw) -> Path:
    return _PANTHEON / "plans" / "tools" / f"{name}.md"


def _report(god: str, category: str, date: str, name: str, **kw) -> Path:
    if not god:
        raise ValueError("Report requires 'god' parameter")
    if date and name:
        raise ValueError("Report accepts 'date' OR 'name', not both")
    base = _ATHENAEUM / f"Codex-God-{god.lower()}" / "reports" / category
    if date:
        return base / f"{date}.md"
    if name:
        return base / f"{name}.md"
    raise ValueError("Report requires 'date' or 'name'")


def _research(god: str, name: str, **kw) -> Path:
    if not god:
        raise ValueError("Research requires 'god' parameter")
    return _ATHENAEUM / f"Codex-God-{god.lower()}" / "research" / name


def _decision(name: str, god: str, **kw) -> Path:
    if god:
        return _ATHENAEUM / f"Codex-God-{god.capitalize()}" / "DECISIONS.md"
    return _PANTHEON / "shared" / "decisions" / f"{name}.md"


def _session(domain: str, name: str, **kw) -> Path:
    return _ATHENAEUM / f"Codex-{domain}" / "sessions" / f"{name}.md"


def _concept(domain: str, name: str, **kw) -> Path:
    return _ATHENAEUM / f"Codex-{domain}" / "distilled" / "concepts" / f"{name}.md"


def _connection(domain: str, name: str, **kw) -> Path:
    return _ATHENAEUM / f"Codex-{domain}" / "distilled" / "connections" / f"{name}.md"


def _skill(name: str, god: str, category: str, **kw) -> Path:
    if god:
        cat = category or god.lower()
        return _HERMES / "profiles" / god.lower() / "skills" / cat / name
    return _HERMES / "skills" / name


def _plugin(name: str, **kw) -> Path:
    return _HERMES / "plugins" / name


def _tool(name: str, **kw) -> Path:
    known = {
        "pantheon-core": _PANTHEON / "pantheon-core" / "mcp_server.py",
        "ichor-gates": _PANTHEON / "lib" / "ichor_gates.py",
        "ichor-mcp": _PANTHEON / "lib" / "ichor_mcp.py",
        "conductor-engine": _PANTHEON / "conductor" / "v2" / "engine.py",
        "pantheon-path": _PANTHEON / "lib" / "pantheon_path.py",
    }
    if name in known:
        return known[name]
    return _PANTHEON / "lib" / f"{name}.py"


def _cron(name: str, god: str, category: str, date: str, **kw) -> Path:
    if not god:
        raise ValueError("Cron output requires 'god' parameter")
    base = _HERMES / "profiles" / god.lower() / "cron" / "output"
    if date:
        return base / date / name if name else base / date
    if category:
        return base / category / name if name else base / category
    return base / name if name else base


# ---------------------------------------------------------------------------
# Register types
# ---------------------------------------------------------------------------

_register("upgrade", _upgrade)
_register("feature", _feature)
_register("idea", _idea)
_register("project_idea", _project_idea)
_register("tool_spec", _tool_spec)
_register("report", _report, needs_god=True, needs_name=False)
_register("research", _research, needs_god=True)
_register("decision", _decision, needs_name=False)
_register("session", _session)
_register("concept", _concept)
_register("connection", _connection)
_register("skill", _skill, needs_god=False)
_register("tool", _tool)
_register("plugin", _plugin)
_register("cron_output", _cron, needs_god=True)

# ---------------------------------------------------------------------------
# Path discipline — check / hint for non-standard paths
# ---------------------------------------------------------------------------


def matches_standard(path: str) -> dict:
    """Check if a filesystem path matches a standard Pantheon path pattern.

    Returns dict with keys: matches (bool), type (str or None), suggestion (str or None).
    """
    p = Path(os.path.expanduser(path)).resolve()
    sp = str(p)

    prefixes = [
        ("upgrade", str(_PANTHEON / "plans/upgrades/")),
        ("feature", str(_PANTHEON / "plans/features/")),
        ("idea", str(_PANTHEON / "plans/ideas/")),
        ("project_idea", str(_PANTHEON / "project-ideas/")),
        ("tool_spec", str(_PANTHEON / "plans/tools/")),
        ("decision", str(_PANTHEON / "shared/decisions/")),
        ("report", str(_ATHENAEUM / "Codex-God-")),
        ("research", str(_ATHENAEUM / "Codex-God-") + "/research/"),
        ("skill_god", str(_HERMES / "profiles/") + "/skills/"),
        ("skill_shared", str(_HERMES / "skills/")),
        ("plugin", str(_HERMES / "plugins/")),
    ]

    for type_name, prefix in prefixes:
        if sp.startswith(prefix):
            return {"matches": True, "type": type_name, "suggestion": None}

    tool_prefix = str(_PANTHEON / "pantheon-core/")
    lib_prefix = str(_PANTHEON / "lib/")
    if sp.startswith(tool_prefix) or sp.startswith(lib_prefix):
        return {"matches": True, "type": "tool", "suggestion": None}

    return {"matches": False, "type": None, "suggestion": None}


def standardize_hint(path: str) -> str:
    """Return a human-readable hint for how to use pantheon_path instead.

    Example:
        standardize_hint("~/athenaeum/Codex-God-thoth/reports/dawn-patrol/2026-07-05.md")
        → 'Use: pantheon_path(type="report", god="thoth", category="dawn-patrol", date="2026-07-05")'
    """
    result = matches_standard(path)
    if not result["matches"]:
        return f"Path '{path}' doesn't match any standard Pantheon path."

    p = Path(os.path.expanduser(path))

    if result["type"] == "report":
        parts = p.relative_to(_ATHENAEUM).parts
        god = parts[0].replace("Codex-God-", "").lower()
        category = parts[2]
        filename = p.stem
        if re.match(r"^\d{4}-\d{2}-\d{2}", filename):
            return f'Use: pantheon_path(type="report", god="{god}", category="{category}", date="{filename}")'
        return f'Use: pantheon_path(type="report", god="{god}", category="{category}", name="{filename}")'

    if result["type"] == "upgrade":
        return f'Use: pantheon_path(type="upgrade", name="{p.name}")'

    if result["type"] == "decision":
        return f'Use: pantheon_path(type="decision", name="{p.stem}")'

    return f'Path "{path}" is a standard path.'
