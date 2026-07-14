"""
control_bridge.py — Control surface adapter for Olympus UI.

Read-only operator surface data: installed plugins, enabled skills,
and integration statuses (delegated to integrations_bridge.py).

Endpoints:
  GET /api/control/plugins     → installed plugin inventory
  GET /api/control/skills      → operator-facing skills list
"""

from __future__ import annotations

import os
import glob
import json
import yaml

from api.helpers import bad, j

# ── Paths ──────────────────────────────────────────────────────────────────
PLUGINS_DIR = os.path.expanduser("~/.hermes/plugins")
SKILLS_DIR = os.path.expanduser("~/.hermes/skills")


# ══════════════════════════════════════════════════════════════════════════════
# Plugins — list installed plugins from ~/.hermes/plugins/
# ══════════════════════════════════════════════════════════════════════════════

def _list_plugins():
    """List installed plugins from the plugins directory."""
    if not os.path.isdir(PLUGINS_DIR):
        return {"plugins": []}

    try:
        entries = sorted(os.listdir(PLUGINS_DIR))
    except OSError:
        return {"plugins": []}

    plugins = []
    for name in entries:
        plugin_path = os.path.join(PLUGINS_DIR, name)
        if not os.path.isdir(plugin_path):
            continue

        # Check for plugin.yaml or __init__.py as existence markers
        has_yaml = os.path.isfile(os.path.join(plugin_path, "plugin.yaml"))
        has_init = os.path.isfile(os.path.join(plugin_path, "__init__.py"))

        # Try to read plugin metadata
        description = ""
        enabled = True  # default assumption

        if has_yaml:
            try:
                with open(os.path.join(plugin_path, "plugin.yaml")) as f:
                    meta = yaml.safe_load(f) or {}
                description = str(meta.get("description", ""))
                enabled = meta.get("enabled", True)
            except Exception:
                pass

        plugins.append({
            "id": name,
            "name": name,
            "description": description or f"Plugin: {name}",
            "enabled": enabled,
            "scope": "extension",
        })

    return {"plugins": plugins}


# ══════════════════════════════════════════════════════════════════════════════
# Skills — list operator-facing skills from ~/.hermes/skills/
# ══════════════════════════════════════════════════════════════════════════════

def _list_skills():
    """List skills with name, description, and category from SKILL.md files."""
    if not os.path.isdir(SKILLS_DIR):
        return {"skills": []}

    try:
        md_files = glob.glob(os.path.join(SKILLS_DIR, "**", "SKILL.md"), recursive=True)
    except OSError:
        return {"skills": []}

    skills = []
    for filepath in sorted(md_files):
        try:
            rel = os.path.relpath(filepath, SKILLS_DIR)
            # Category is the parent directory (if not at root)
            parts = rel.split(os.sep)
            category = parts[0] if len(parts) > 1 else "general"
            skill_name = os.path.basename(os.path.dirname(filepath))

            # Parse frontmatter for description
            description = ""
            with open(filepath) as f:
                content = f.read(2000)

            # Simple frontmatter extraction
            if content.startswith("---"):
                end = content.find("---", 3)
                if end > 0:
                    try:
                        fm = yaml.safe_load(content[3:end]) or {}
                        description = str(fm.get("description", ""))
                    except Exception:
                        pass

            skills.append({
                "id": skill_name,
                "name": skill_name.replace("-", " ").replace("_", " ").title(),
                "description": description or f"Skill: {skill_name}",
                "category": category,
                "enabled": True,
            })
        except Exception:
            continue

    return {"skills": skills}


# ══════════════════════════════════════════════════════════════════════════════
# Route handler
# ══════════════════════════════════════════════════════════════════════════════

def handle_control(handler, parsed):
    path = parsed.path

    if path == "/api/control/plugins":
        return j(handler, _list_plugins())

    if path == "/api/control/skills":
        return j(handler, _list_skills())

    return False
